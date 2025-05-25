document.getElementById('clear_btn').addEventListener('click', function() {
const confirmClear = confirm("Are you sure you want to clear all form fields?");

if (confirmClear) {
    const inputs = document.querySelectorAll('input');
    
    inputs.forEach(input => {
    input.value = '';
    });
}
});

function convertToWords(input) {
    const num = parseInt(input.value);
    const targetId = "words-" + input.name;
    const outputDiv = document.getElementById(targetId);

    if (!input.value || isNaN(num)) {
        outputDiv.innerText = '';
        return;
    }

    const ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
                  'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen',
                  'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen'];
    const tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety'];

    function numToWords(n, s) {
        let str = '';
        if (n > 19) {
            str += tens[Math.floor(n / 10)] + ' ' + ones[n % 10];
        } else {
            str += ones[n];
        }
        if (n !== 0) str += ' ' + s;
        return str;
    }

    let output = '';
    output += numToWords(Math.floor(num / 10000000), 'Crore ');
    output += numToWords(Math.floor((num / 100000) % 100), 'Lakh ');
    output += numToWords(Math.floor((num / 1000) % 100), 'Thousand ');
    output += numToWords(Math.floor((num / 100) % 10), 'Hundred ');
    if (num > 100 && num % 100 > 0) output += ' and ';
    output += numToWords(num % 100, '');

    outputDiv.innerText = output.trim();
}
